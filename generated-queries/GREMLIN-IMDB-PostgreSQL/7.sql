SELECT count(*)
FROM aka_name, cast_info, char_name, info_type, movie_info, name, title
WHERE char_name.name = 'Himself'
  AND title.imdb_index = 'XII'
  AND aka_name.person_id = name.id
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND cast_info.person_role_id = char_name.id
  AND movie_info.info_type_id = info_type.id
  AND movie_info.movie_id = title.id;
