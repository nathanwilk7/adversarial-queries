SELECT count(*)
FROM aka_name, cast_info, char_name, keyword, kind_type, movie_keyword, movie_link, name, person_info, title
WHERE char_name.name = 'Himself'
  AND aka_name.person_id = name.id
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND cast_info.person_role_id = char_name.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.linked_movie_id = title.id
  AND person_info.person_id = name.id
  AND title.kind_id = kind_type.id;
