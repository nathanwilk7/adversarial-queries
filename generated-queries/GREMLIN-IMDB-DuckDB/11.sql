SELECT count(*)
FROM aka_name, cast_info, keyword, movie_keyword, name, person_info, role_type, title
WHERE cast_info.nr_order = 0
  AND aka_name.person_id = name.id
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND cast_info.role_id = role_type.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id
  AND person_info.person_id = name.id;
