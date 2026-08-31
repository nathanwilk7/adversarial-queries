SELECT count(*)
FROM aka_name, cast_info, comp_cast_type, complete_cast, keyword, movie_keyword, name, person_info, title
WHERE comp_cast_type.kind = 'complete+verified'
  AND aka_name.person_id = name.id
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND complete_cast.movie_id = title.id
  AND complete_cast.status_id = comp_cast_type.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id
  AND person_info.person_id = name.id;
